import tensorflow as tf
import numpy as np 
import time 
import matplotlib.pyplot as plt

import os
os.environ['TF_CPP_MIN_LOG_LEVEL'] = '2'

def activation_function(mu):
    M=20
    return (1/M)*(tf.nn.softplus(tf.cast(M*(mu+1.0),tf.float32))-np.log(1.0+np.exp(M)))


def lambda_qut_sann_regression(inputx,nSample=100000,miniBatchSize=500,alpha=0.05,option='quantile'):
    if np.mod(nSample, miniBatchSize)==0:
        offset=0
    else:
        offset=1
    
    n,p1 = inputx.shape    
    fullList =np.zeros((miniBatchSize*(nSample//miniBatchSize+offset),))
    
    for index in range(nSample//miniBatchSize+offset):
        # loc and scale could be anything since the statistics is pivotal
        ySample =np.random.normal(loc=0., scale=1, size=(n, 1,miniBatchSize)).astype(np.float32) 
        yBar =np.mean(ySample, axis=0)
        normFactor = tf.sqrt(tf.reduce_sum(tf.square(yBar-ySample), axis=0))
        xySum = tf.reduce_sum((ySample - yBar) *np.repeat(np.expand_dims(inputx, axis=2), miniBatchSize, axis=2), axis=0).numpy()
        infnorm =np.amax(np.abs(xySum), axis=0)
        
        x = tf.constant(0.)
        with tf.GradientTape() as g:
            g.watch(x)
            y = activation_function(x)
        dy_dx = tf.cast(g.gradient(y,x), tf.float32) 

        stat = dy_dx / normFactor * infnorm

        fullList[index*miniBatchSize:(index+1)*miniBatchSize]=stat[:]
 
    if option=='full':
        return fullList
    elif option=='quantile':
        return np.quantile(fullList, 1-alpha)
    else:
        pass

def shrinkage_operator(u,lambda_):
    return np.sign(u) * np.maximum((np.abs(u) - lambda_), 0.)
   
def TFmodel(Xsample,Ysample,p2,activation_function,lamb,learningRate,withSD,
            ifTrain=True,iterationISTA=3000, Xtest=None, iniscale=0.01,
            rel_err=1.e-9, w1_ini=None, w2_ini=None, b2_ini=None):
    
    n,p1 = Xsample.shape
  
    if w1_ini is None:
        w1_ini = np.random.normal(loc=0., scale=iniscale, size=(p2,p1))
    if w2_ini is None:
        w2_ini =np.random.normal(loc=0., scale=iniscale, size=(1,p2))
        w2_ini[0] = 10*iniscale
    if b2_ini is None:
        b2_ini = np.random.normal(loc=0., scale=iniscale, size=(1,1))
                 
    w1 = tf.Variable(w1_ini ,shape=(p2,p1), trainable=True,dtype=tf.float32)
    w2 = tf.Variable(w2_ini ,shape=(1,p2), trainable=True,dtype=tf.float32)
    b2 = tf.Variable(b2_ini ,shape=(1,1), trainable=True,dtype=tf.float32)
    
    t=1        
    w1_y=tf.Variable(w1_ini ,shape=(p2,p1), trainable=True,dtype=tf.float32)
    w2_y=tf.Variable(w2_ini ,shape=(1,p2), trainable=True,dtype=tf.float32)
    b2_y=tf.Variable(b2_ini ,shape=(1,1), trainable=True,dtype=tf.float32)

    def evaluate(examx, examy, ifUpdate=True, ifISTA=False):
        nonlocal w1
        nonlocal w2 
        nonlocal b2 
        nonlocal w1_y
        nonlocal w2_y
        nonlocal b2_y
        nonlocal t

        # new structure in TF2.0 to track the parts of computation that will need backprop
        with tf.GradientTape(persistent=True) as g:
            g.watch([w1_y,w2_y,b2_y])
            w1X=tf.matmul(w1_y,tf.transpose(examx))
            w2_l2normalized_1=tf.nn.l2_normalize(tf.cast(w2_y,tf.float32),1)
            yhat =tf.matmul(w2_l2normalized_1,activation_function(w1X))+tf.matmul(b2_y,np.ones([1,n],dtype=np.float32))
            bareCost = tf.sqrt(tf.cast(tf.reduce_sum(tf.square(yhat-examy),axis=1),tf.float32)) # sqrt Lasso
            cost=bareCost + lamb*tf.reduce_sum(tf.abs(w1_y))
        if not (ifISTA):
            w1_gra   = g.gradient(cost, w1_y)
        if (ifISTA):
            bare_w1_gra = g.gradient(bareCost, w1_y)
        w2_gra = g.gradient(cost, w2_y)
        b2_gra = g.gradient(cost, b2_y)
        del g
        
        w1_value=w1.numpy()###record the last step value
        w2_value=w2.numpy()
        b2_value=b2.numpy()
        
        if (ifUpdate):
            if (ifISTA):
                proposed_w1 = shrinkage_operator(w1_y-bare_w1_gra*learningRate,lamb*learningRate)
            else:
                proposed_w1 = w1_y-learningRate*w1_gra
            proposed_w2 = w2_y - learningRate*w2_gra  ###normalize
            proposed_b2 = b2_y - learningRate*b2_gra
            w1.assign(proposed_w1)
            w2.assign(proposed_w2)
            b2.assign(proposed_b2)
            
            t_1=(1+np.sqrt(1+4*(t**2)))/2
             
            w1_atProposition = w1.numpy()
            w2_atProposition = w2.numpy()
            b2_atProposition = b2.numpy()
             
            w1_y=tf.Variable(w1_atProposition+(t-1)/t_1*(w1_atProposition-w1_value),shape=(p2,p1), trainable=True)
            w2_y=tf.Variable(w2_atProposition+(t-1)/t_1*(w2_atProposition-w2_value),shape=(1,p2), trainable=True)
            b2_y=tf.Variable(b2_atProposition+(t-1)/t_1*(b2_atProposition-b2_value),shape=(1,1), trainable=True)
        
            t=t_1
            
            w1X_atProposition=tf.matmul(w1_atProposition ,tf.transpose(examx))
            w2_normalized_atProposition=tf.nn.l2_normalize(tf.cast(w2_atProposition,tf.float32),1).numpy()
            yhat_atProposition =tf.matmul(w2_normalized_atProposition,activation_function(w1X_atProposition))+b2_atProposition
            bareCost_atProposition = tf.sqrt(tf.cast(tf.reduce_sum(tf.square(yhat_atProposition-examy),axis=1),tf.float32))
            cost_atProposition=bareCost_atProposition +lamb*tf.reduce_sum(tf.abs(w1_atProposition))
        return cost_atProposition
    
    if (ifTrain):
        bestcost=float('inf')
        cont=withSD
        epoch=0
        #for epoch in range(iterationSD):      # steepest descent part
        while(cont):
            if epoch % 100 == 0 and epoch != 0:
                cost = evaluate(Xsample, Ysample, ifUpdate=True, ifISTA=False)
                print('         At epoch', epoch,'cost =', cost.numpy())
                if(cost<bestcost):
                    bestcost=cost
                else:
                    cont=False
            cost = evaluate(Xsample, Ysample, ifUpdate=True, ifISTA=False)
            epoch +=1

        bestcost=float('inf')
        epoch=0
        cont=True
        while(cont):
        #for epoch in range(iterationISTA):    # ISTA part           
            if epoch % 100 == 0 and epoch != 0:
                #pass
                print('         At epoch FISTA', epoch,'cost =', cost.numpy())
                if(cost>bestcost):
                    learningRate *= .99
                    print(learningRate)
                if(np.abs(cost-bestcost)/cost<rel_err):
                    print('stop reason: rel_err')
                    cont=False
                bestcost=cost      
            cost = evaluate(Xsample, Ysample, ifUpdate=True, ifISTA=True)
            cont = (epoch<iterationISTA) & cont
            if(cont==False):
                print('stop reason: max iteration steps')
            epoch += 1
            
    w1X=tf.matmul(w1,tf.transpose(Xsample))
    w2_l2normalized=tf.nn.l2_normalize(tf.cast(w2,tf.float32),1)
    yhat=tf.matmul(w2_l2normalized,activation_function(w1X))+tf.matmul(b2,np.ones([1,n]))
    yhat=tf.transpose(yhat)
    
    if np.any(Xtest):
        ntest,p1test = Xtest.shape
        w1X=tf.matmul(w1,tf.transpose(Xtest))
        mutesthat=tf.matmul(w2_l2normalized,activation_function(w1X))+tf.matmul(b2,np.ones([1,ntest]))
    else:
        mutesthat = None
        
    w1 = w1.numpy()
    return [w1,w2,b2,yhat,mutesthat,cost,learningRate]

def TFmodelfit(X,y,p2,activation_function,lamb,learningRate0,withSD,ifTrain=True,iterationISTA=3000, Xtest=None, iniscale=0.01):
 
    lro=learningRate0[0]
    [w10, w20,b20,yhat0,mutesthat0,cost0,lro_0] = TFmodel(X,y,p2,activation_function,lamb,lro,withSD=False,ifTrain=True,iterationISTA=-999,Xtest=Xtest, iniscale=iniscale,rel_err=1.e-5)
    [w1o, w2o,b2o,yhato,mutesthato,costo,lro_o] = TFmodel(X,y,p2,activation_function,lamb,lro_0,withSD,ifTrain=True,iterationISTA=iterationISTA, Xtest=Xtest, iniscale=iniscale, rel_err=1.e-9, w1_ini=w10, w2_ini=w20, b2_ini=b20)

    for lr in learningRate0[1:]:
        [w1oo,w2oo,b2oo,yhatoo,mutesthatoo,costoo,lro_oo] = TFmodel(X,y,p2,activation_function,lamb,lr,withSD,ifTrain=True,iterationISTA=iterationISTA,Xtest=Xtest,iniscale=iniscale,rel_err=1.e-9, w1_ini=w10, w2_ini=w20, b2_ini=b20)
        if(costoo<costo):
            costo=costoo
            w1o=w1oo
            w2o=w2oo
            b2o=b2oo
            yhato=yhatoo
            mutesthato=mutesthatoo
            lro_o=lro_oo
        else:
            break
    return [w1o, w2o,b2o,yhato,mutesthato,costo,lro_o]

def resultanalysis(w1o,y_test,mutesthato,needles_index_true=None):
    p1=w1o.shape[1]
    needles_index_hat=np.array(np.where(np.sum(abs(w1o[:,0:(p1-1)]),axis=0)>0),dtype=float)+1
    if np.any(needles_index_true)!=None:
        s=len(needles_index_true)
        all_index=np.arange(1,p1)
        noneedles_index_true=np.delete(all_index,np.where(np.isin(all_index,needles_index_true)))
        
        tp_index=needles_index_hat[np.where(np.isin(needles_index_hat,needles_index_true)==True)]
        fp_index=needles_index_hat[np.where(np.isin(needles_index_hat,noneedles_index_true)==True)]
        tpr=len(tp_index)/s
        fdr=len(fp_index)/np.max([needles_index_hat.shape[1],1])
        
        hatintrue=np.where(np.isin(needles_index_hat,needles_index_true)==True)[1]
        trueinhat=np.where(np.isin(needles_index_true,needles_index_hat)==True)
        if np.all(hatintrue==trueinhat)&(len(hatintrue)!=0):#######
            hat_equal_true=True
        else:
            hat_equal_true=False
    else:
        tpr=None
        fdr=None
        hat_equal_true=None
    ##predictive error
    pe=tf.reduce_sum(tf.square(y_test-mutesthato),axis=1)/y_test.shape[1]
    return needles_index_hat,tpr,fdr,hat_equal_true,pe

